using System;
using System.IO;
using System.IO.Pipes;
using System.Net;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Threading;

internal sealed class ReleaseService : ServiceBase
{
    private const string PipeName = "ComiTrans.ReleaseCheck";
    private const string ReleaseApi = "https://api.github.com/repos/Aaaaamadeus/ComiTrans/releases/latest";
    private const int ResponseLimit = 512 * 1024;
    private readonly ManualResetEvent stopped = new ManualResetEvent(false);
    private Thread listener;

    private ReleaseService() { ServiceName = "ComiTransReleaseCheck"; }

    public static void Main()
    {
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        Run(new ReleaseService());
    }

    protected override void OnStart(string[] args)
    {
        stopped.Reset();
        listener = new Thread(Listen) { IsBackground = true };
        listener.Start();
    }

    protected override void OnStop()
    {
        stopped.Set();
        listener.Join(7000);
    }

    private void Listen()
    {
        var acl = new PipeSecurity();
        var users = new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null);
        var network = new SecurityIdentifier(WellKnownSidType.NetworkSid, null);
        var service = new SecurityIdentifier(WellKnownSidType.LocalServiceSid, null);
        acl.AddAccessRule(new PipeAccessRule(network, PipeAccessRights.FullControl, AccessControlType.Deny));
        acl.AddAccessRule(new PipeAccessRule(users, PipeAccessRights.Read, AccessControlType.Allow));
        acl.AddAccessRule(new PipeAccessRule(service, PipeAccessRights.FullControl, AccessControlType.Allow));
        while (!stopped.WaitOne(0))
        {
            try
            {
                using (var pipe = new NamedPipeServerStream(PipeName, PipeDirection.Out, 1,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 0, 0, acl))
                {
                    var pending = pipe.BeginWaitForConnection(null, null);
                    using (var ready = pending.AsyncWaitHandle)
                    {
                        if (WaitHandle.WaitAny(new[] { stopped, ready }) == 0) return;
                        pipe.EndWaitForConnection(pending);
                    }
                    var data = ReadRelease();
                    if (data.Length == 0) continue;
                    var write = pipe.BeginWrite(data, 0, data.Length, null, null);
                    using (var ready = write.AsyncWaitHandle)
                    {
                        if (WaitHandle.WaitAny(new[] { stopped, ready }, 1000) == 1) pipe.EndWrite(write);
                    }
                }
            }
            catch (IOException) { stopped.WaitOne(250); }
            catch (UnauthorizedAccessException) { stopped.WaitOne(1000); }
            catch (WebException) { }
        }
    }

    private static byte[] ReadRelease()
    {
        var request = (HttpWebRequest)WebRequest.Create(ReleaseApi);
        request.UserAgent = "ComiTrans-ReleaseService";
        request.Accept = "application/vnd.github+json";
        request.AllowAutoRedirect = false;
        request.Timeout = 4500;
        request.ReadWriteTimeout = 1000;
        using (var response = (HttpWebResponse)request.GetResponse())
        using (var stream = response.GetResponseStream())
        using (var output = new MemoryStream())
        {
            if (response.StatusCode != HttpStatusCode.OK || response.ContentLength > ResponseLimit) return new byte[0];
            var buffer = new byte[8192];
            int count;
            while ((count = stream.Read(buffer, 0, buffer.Length)) > 0)
            {
                if (output.Length + count > ResponseLimit) return new byte[0];
                output.Write(buffer, 0, count);
            }
            return output.ToArray();
        }
    }
}
